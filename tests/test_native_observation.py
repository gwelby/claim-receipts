"""C2 (Codex, fdb8f87): native observation must not overstate execution, completeness or identity.

Every case here is one row of Codex's executed native comparison (observations/COMPARISON.json),
rebuilt on the production path: the real ledger hooks record each call, a synthetic Hermes-shaped
transcript (assistant tool_calls -> tool rows keyed by tool_call_id, JSON output envelopes) carries
what the call printed, real local commands run only on throwaway files, and receipt.build — what the
end hook writes — gives the verdict. Each negative is paired with the positive that must survive.

A case is a regression control: on fdb8f87 the NEGATIVE rows fail and the read_file positive fails.
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

from receipts import ledger, receipt, transcript  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<62} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-native-obs-"))
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

    def call(self, tool, args, run, envelope=None):
        self.n += 1
        cid = f"call-{self.n}"
        self._row("assistant", calls=[{"id": cid, "function": {"name": tool,
                                                               "arguments": json.dumps(args)}}])
        kw = dict(tool_name=tool, args=args, session_id=self.name, tool_call_id=cid)
        ledger.pre_tool_call(**kw)
        out, rc = run()
        ledger.post_tool_call(**kw, result=out, status="ok" if rc == 0 else "error")
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

    def read_file(self, path, envelope=None):
        def run():
            try:
                return pathlib.Path(path).read_text(), 0
            except OSError as exc:
                return str(exc), 1
        return self.call("read_file", {"path": str(path)}, run, envelope)

    def verdict(self, claim):
        self._row("assistant", claim)
        self.con.close()
        d = receipt.build(self.name, db_path=self.db)
        vs = d["verdicts"]
        return (vs[0]["verdict"], vs[0]["reason"]) if len(vs) == 1 else ("UNJUDGED", str(len(vs)))


def expect(label, got, allowed):
    check(label, got[0] in allowed, f"{got[0]}/{got[1]} (want {'|'.join(allowed)})")


# ---------------------------------------------------------------- O2: hidden names
s = Session("hidden_without_all")
t = s.scope / ".secret.md"
t.write_text("present, omitted by default ls\n")
(s.scope / "visible.md").write_text("v\n")
s.sh("ls -1 " + q(s.scope))
expect("C2 NEG default ls omitting a dotfile cannot back its absence", s.verdict(
    f"The file {t} is missing."), ["UNVERIFIABLE"])

s = Session("hidden_with_all_positive")
t = s.scope / ".secret.md"
t.write_text("present and listed\n")
s.sh("ls -1A " + q(s.scope))
expect("C2 POS ls -1A printing the dotfile contradicts its absence", s.verdict(
    f"The file {t} is missing."), ["CONTRADICTED"])

s = Session("default_ls_visible_absence_positive")
(s.scope / "visible.md").write_text("v\n")
s.sh("ls -1 " + q(s.scope))
expect("C2 POS default ls still backs absence of a VISIBLE name", s.verdict(
    f"The file {s.scope / 'gone.md'} is missing."), ["BACKED"])

# ---------------------------------------------------------------- O1: quoted separator
s = Session("quoted_separator")
t = s.scope / "present.md"
t.write_text("present; no listing executes\n")
s.sh("printf '%s\\n' " + shlex.quote("note; ls " + str(s.scope)))
expect("C2 NEG quoted '; ls ROOT' inside printf is not a listing", s.verdict(
    f"The file {t} is missing."), ["UNVERIFIABLE"])

s = Session("empty_scope_absence_positive")
s.sh("ls -1A " + q(s.scope))
expect("C2 POS complete ls -1A of an empty scope backs absence", s.verdict(
    f"The file {s.scope / 'missing.md'} is missing."), ["BACKED"])

s = Session("columns_presence_positive")
for n in ("alpha.md", "middle.md", "zeta.md"):
    (s.scope / n).write_text("x\n")
s.sh("ls -C " + q(s.scope))
expect("C2 POS a name among ls -C columns contradicts absence", s.verdict(
    f"The file {s.scope / 'middle.md'} is missing."), ["CONTRADICTED"])

# ---------------------------------------------------------------- O2: reader truncation
s = Session("reader_truncation")
t = s.scope / "zzzz_present.md"
for i in range(180):
    (s.scope / (f"a{i:03d}_" + "x" * 119 + ".md")).write_text("")
t.write_text("sorts after the reader cutoff\n")
out = s.sh("ls -1A " + q(s.scope))
check("  (setup) real listing exceeds the reader cap and the cut drops the target",
      len(out) > transcript.MAX_OUTPUT_CHARS and t.name not in out[:transcript.MAX_OUTPUT_CHARS],
      f"{len(out)} chars")
expect("C2 NEG a listing cut by the reader cannot back absence", s.verdict(
    f"The file {t} is missing."), ["UNVERIFIABLE"])

# ---------------------------------------------------------------- O3: location identity
s = Session("recursive_location_alias")
(s.scope / "a").mkdir()
(s.scope / "b").mkdir()
(s.scope / "b" / "subject.md").write_text("other directory\n")
s.sh("find " + q(s.scope))
expect("C2 NEG find printing b/subject.md cannot contradict a/subject.md absence", s.verdict(
    f"The file {s.scope / 'a' / 'subject.md'} is missing."), ["BACKED", "UNVERIFIABLE"])

s = Session("recursive_exact_presence_positive")
(s.scope / "a").mkdir()
(s.scope / "a" / "subject.md").write_text("exact target\n")
s.sh("find " + q(s.scope))
expect("C2 POS find printing the exact target contradicts absence", s.verdict(
    f"The file {s.scope / 'a' / 'subject.md'} is missing."), ["CONTRADICTED"])

# ---------------------------------------------------------------- O3: call/order identity
s = Session("repeated_present_then_absent")
t = s.scope / "subject.md"
t.write_text("present for the first call\n")
cmd = "ls -1A " + q(s.scope)
s.sh(cmd)
s.sh("rm -- " + q(t))
s.sh(cmd)
expect("C2 NEG an older identical listing cannot contradict the newest", s.verdict(
    f"The file {t} is missing."), ["BACKED", "UNVERIFIABLE"])

s = Session("repeated_absent_then_present_positive")
t = s.scope / "subject.md"
cmd = "ls -1A " + q(s.scope)
s.sh(cmd)
s.sh("printf '%s\\n' present > " + q(t))
s.sh(cmd)
expect("C2 POS the newest listing printing the target contradicts absence", s.verdict(
    f"The file {t} is missing."), ["CONTRADICTED"])

# ---------------------------------------------------------------- O4/O5: hedge admission
s = Session("grounded_cat_hedge_positive")
t = s.scope / "subject.md"
t.write_text("content\n")
s.sh("cat " + q(t))
expect("C2 POS successful cat of the exact subject backs the hedge", s.verdict(
    f"I could not confirm {t}."), ["BACKED"])

s = Session("same_basename_unrelated_hedge")
(s.scope / "requested").mkdir()
(s.scope / "other").mkdir()
(s.scope / "other" / "report.md").write_text("unrelated\n")
s.sh("cat " + q(s.scope / "other" / "report.md"))
expect("C2 NEG reading other/report.md is not observing requested/report.md", s.verdict(
    f"I could not confirm {s.scope / 'requested' / 'report.md'}."), ["UNBACKED"])

s = Session("false_command_hedge")
t = s.scope / "unobserved.md"
s.sh("false " + q(t))
expect("C2 NEG failed `false TARGET` is no observation (`false` contains `ls`)", s.verdict(
    f"I could not confirm {t}."), ["UNBACKED"])

s = Session("unscoped_printf_hedge")
s.sh("printf '%s\\n' 'plain uninformative output'")
expect("C2 NEG unrelated printf output is no attempted verification", s.verdict(
    "I could not confirm the track exists."), ["UNBACKED"])

s = Session("read_file_grounded_hedge_positive")
t = s.scope / "subject.md"
t.write_text("a genuine native read-file observation of the named subject\n")
s.read_file(t)
expect("C2 POS exact-path native read_file backs the hedge (f4 BACKED)", s.verdict(
    f"I could not confirm {t}."), ["BACKED"])

s = Session("read_file_hermes_content_envelope_positive")
t = s.scope / "subject.md"
t.write_text("line\n")
s.read_file(t, envelope=lambda out, rc: {"content": "1|" + out, "total_lines": 1,
                                         "truncated": False})
expect("C2 POS read_file in Hermes's {content: ...} envelope also binds", s.verdict(
    f"I could not confirm {t}."), ["BACKED"])

# ---------------------------------------------------------------- adjacent shapes, same bounds
# Not Codex rows: the same admission rules applied to neighbouring spellings, so the fix is not
# keyed to one sentence or one command shape.
s = Session("adj_other_segment_output_unbound")
(s.scope / "a").mkdir()
(s.scope / "b").mkdir()
(s.scope / "b" / "subject.md").write_text("x\n")
s.sh(f"ls -1A {q(s.scope / 'a')}; ls -1A {q(s.scope / 'b')}")
expect("ADJ NEG a co-segment's lines are not this listing's entries", s.verdict(
    f"The file {s.scope / 'a' / 'subject.md'} is missing."), ["BACKED", "UNVERIFIABLE"])

s = Session("adj_redirected_listing")
(s.scope / "present.md").write_text("x\n")
s.sh(f"ls -1A {q(s.scope)} > /dev/null")
expect("ADJ NEG a redirected listing's empty capture is not an empty scope", s.verdict(
    f"The file {s.scope / 'present.md'} is missing."), ["UNVERIFIABLE"])

s = Session("adj_ls_dash_d")
(s.scope / "present.md").write_text("x\n")
s.sh("ls -d " + q(s.scope))
expect("ADJ NEG ls -d lists the directory itself, not its contents", s.verdict(
    f"The file {s.scope / 'present.md'} is missing."), ["UNVERIFIABLE"])

s = Session("adj_command_substitution")
(s.scope / "present.md").write_text("x\n")
s.sh(f"echo \"$(ls -1A {q(s.scope / 'nope')} 2>&1)\"")
expect("ADJ NEG command substitution is not an admitted listing", s.verdict(
    f"The file {s.scope / 'present.md'} is missing."), ["UNVERIFIABLE"])

s = Session("adj_ls_recursive_location")
(s.scope / "a").mkdir()
(s.scope / "b").mkdir()
(s.scope / "b" / "subject.md").write_text("x\n")
s.sh("ls -1AR " + q(s.scope))
expect("ADJ NEG ls -R section b/ cannot contradict a/subject.md", s.verdict(
    f"The file {s.scope / 'a' / 'subject.md'} is missing."), ["BACKED", "UNVERIFIABLE"])

s = Session("adj_ls_recursive_exact_positive")
(s.scope / "b").mkdir()
(s.scope / "b" / "subject.md").write_text("x\n")
s.sh("ls -1AR " + q(s.scope))
expect("ADJ POS ls -R printing the target in its section contradicts", s.verdict(
    f"The file {s.scope / 'b' / 'subject.md'} is missing."), ["CONTRADICTED"])

s = Session("adj_failed_cat_exact_subject")
t = s.scope / "absent.md"
s.sh("cat " + q(t))
expect("ADJ NEG a failed cat of the exact subject is no observation", s.verdict(
    f"I could not confirm {t}."), ["UNBACKED"])

s = Session("adj_mkdir_is_not_observation")
t = s.scope / "details"
s.sh("mkdir " + q(t))
expect("ADJ NEG mkdir .../details is not an observe verb (dir/tail substrings)", s.verdict(
    f"I could not confirm {t}."), ["UNBACKED"])

s = Session("adj_read_file_other_path")
(s.scope / "other").mkdir()
(s.scope / "other" / "subject.md").write_text("x\n")
s.read_file(s.scope / "other" / "subject.md")
expect("ADJ NEG read_file of a same-basename path does not ground the hedge", s.verdict(
    f"I could not confirm {s.scope / 'subject.md'}."), ["UNBACKED"])

s = Session("adj_read_file_error")
t = s.scope / "subject.md"
s.read_file(t, envelope=lambda out, rc: {"error": "File not found: " + str(t)})
expect("ADJ NEG a read_file error envelope is no observation", s.verdict(
    f"I could not confirm {t}."), ["UNBACKED"])

s = Session("adj_host_truncated_listing")
t = s.scope / "present.md"
t.write_text("x\n")
s.call("terminal", {"command": "ls -1A " + q(s.scope)},
       lambda: ("a.md\n[truncated 1,204 chars; full output saved]\n", 0))
expect("ADJ NEG host-marked truncated output cannot back absence", s.verdict(
    f"The file {t} is missing."), ["UNVERIFIABLE"])

s = Session("adj_newest_listing_failed")
t = s.scope / "subject.md"
t.write_text("x\n")
s.sh("ls -1A " + q(s.scope))
s.sh("rm -- " + q(t))
s.sh("ls -1A " + q(s.scope / "nope"))       # fails; covers nothing about scope -> older stands
s.sh("ls -1A " + q(s.scope) + " | head -1")  # newest covering listing is filtered
expect("ADJ NEG an older listing is not substituted for a newer filtered one", s.verdict(
    f"The file {t} is missing."), ["BACKED", "UNVERIFIABLE"])

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — native observations are bound to execution, completeness and identity")
sys.exit(1 if fails else 0)

"""Regression controls for Codex's fdb8f87 HOLD, cases C1 and C3 (receipts/judge.py).

C1 — count coverage was treated as proof of the claimed property: injected counts 2/2 plus a
     joined 53% measurement returned BACKED/scope-covered for "All 2 images are full-page."
     Counts are admission only; the claim's kind is still judged, and a favorable single-subject
     verdict cannot speak for the whole extent (it abstains).
C3 — a successful command that merely NAMED the target by substring erased a recorded target
     failure: `check report.md.bak`, another directory's report.md, or printf text each gave
     BACKED for "I fixed <target>". A repair is now the identical failing command re-run, or an
     exact-path write; any other success naming the subject abstains.

Every negative has its paired positive control, and the C3 cases run through the plugin's real
registered hooks on synthetic files (no real session, store, network or checker).
"""
import copy
import importlib.util
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from receipts.evidence import Evidence             # noqa: E402
from receipts.judge import extract_claims, judge   # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<62} {detail}")
    if not cond:
        fails.append(name)


CASES = {c["id"]: c for c in json.loads((ROOT / "fixtures" / "acceptance.json").read_text())["cases"]}


def fixture_verdict(case, claimed=None, evidence=None):
    claim = extract_claims(case["claim_text"])[0]
    if case.get("subject"):
        claim.subject = case["subject"]
    scope = case.get("scope") or {}
    v = judge(claim, Evidence.from_fixture(case),
              claimed_count=claimed if claimed is not None else scope.get("claimed"),
              evidence_count=evidence if evidence is not None else scope.get("evidence"))
    return v


def r2a_with(pct):
    """Codex's exact C1 input: the exposed r2a fixture, first measurement rewritten."""
    case = copy.deepcopy(CASES["case-r2a"])
    case["tool_outputs"][0]["output"] = f"ink bbox partial; coverage {pct}%"
    return case


print("C1 — bound scope is admission, not property proof")

v = fixture_verdict(r2a_with(53), claimed=2, evidence=2)
check("C1 decisive: counts 2/2 + joined 53% is not BACKED", v.verdict != "BACKED",
      f"{v.verdict}/{v.reason}")
check("C1 decisive: the kind is judged -> measurement-disagrees",
      (v.verdict, v.reason) == ("CONTRADICTED", "measurement-disagrees"), f"{v.verdict}/{v.reason}")

case = r2a_with(100)
case["tool_outputs"][1]["output"] = "ink bbox full; coverage 100%"
v = fixture_verdict(case, claimed=2, evidence=2)
check("C1 retired branch: counts 2/2 + all 100% abstains, not BACKED",
      (v.verdict, v.reason) == ("UNVERIFIABLE", "scope-property-unbound"), f"{v.verdict}/{v.reason}")

v = fixture_verdict(CASES["case-r2a"])
check("C1 keep: unbound aggregate (no counts) abstains",
      (v.verdict, v.reason) == ("UNVERIFIABLE", "scope-unbindable"), f"{v.verdict}/{v.reason}")

v = fixture_verdict(CASES["case-03"])
check("C1 keep: narrower evidence count stays UNBACKED/scope-narrower",
      (v.verdict, v.reason) == ("UNBACKED", "scope-narrower"), f"{v.verdict}/{v.reason}")

v = fixture_verdict(CASES["case-r3d"])
check("C1 paired positive: single-subject coverage stays BACKED",
      (v.verdict, v.reason) == ("BACKED", "measurement-agrees"), f"{v.verdict}/{v.reason}")


# ----------------------------------------------------------------- native, registered hooks
tmp = tempfile.mkdtemp(prefix="receipts-judge-identity-")

spec = importlib.util.spec_from_file_location(
    "receipts_plugin_under_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class Ctx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_command(self, name, handler, **kwargs):
        pass


ctx = Ctx()
plugin.register(ctx)


class Session:
    """Synthetic session through the real hooks; tool results are recorded, never executed."""

    def __init__(self, name):
        self.name = name
        self.dir = pathlib.Path(tmp) / name
        (self.dir / "data").mkdir(parents=True)
        self.db = self.dir / "state.db"
        os.environ["RECEIPTS_ROOT"] = str(self.dir / "data")
        os.environ["RECEIPTS_TRANSCRIPT_DB"] = str(self.db)
        self.con = sqlite3.connect(self.db)
        self.con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
                         "role TEXT, content TEXT, tool_name TEXT, timestamp TEXT)")
        self.call = 0

    def message(self, role, content, tool=None):
        self.con.execute("INSERT INTO messages (session_id,role,content,tool_name,timestamp) "
                         "VALUES (?,?,?,?,?)", (self.name, role, content, tool, "2026-11-10T22:00:00Z"))
        self.con.commit()

    def tool(self, name, args, action=None, status="ok", output=""):
        self.call += 1
        kw = dict(tool_name=name, args=args, session_id=self.name, tool_call_id=f"call-{self.call}")
        ctx.hooks["pre_tool_call"](**kw)
        if action:
            action()
        ctx.hooks["post_tool_call"](**kw, result=output, status=status)
        self.message("tool", output, name)

    def finish(self, text):
        self.message("assistant", text)
        ctx.hooks["on_session_end"](session_id=self.name)
        self.con.close()
        saved = self.dir / "data" / "receipts" / f"{self.name}.json"
        d = json.loads(saved.read_text()) if saved.is_file() else {"verdicts": []}
        vs = d.get("verdicts") or []
        return (vs[0]["verdict"], vs[0]["reason"]) if len(vs) == 1 else ("UNJUDGED", str(len(vs)))


def command_case(name, later):
    """Codex's command-identity shape: write target, target check fails, then `later` succeeds."""
    s = Session(name)
    target = s.dir / "target" / "report.md"
    target.parent.mkdir()
    s.tool("write_file", {"path": str(target)}, lambda: target.write_text("initial work\n"))
    s.tool("terminal", {"command": f"check {target}"}, status="error", output="target check failed")
    if later is not None:
        cmd = later(s, target)
        s.tool("terminal", {"command": cmd}, status="ok", output="command completed")
    return s, target


print("\nC3 — command identity (registered hooks, synthetic files)")

s, t = command_case("exact_rerun_positive", lambda s, t: f"check {t}")
got = s.finish(f"I fixed `{t}`.")
check("C3 paired positive: identical check re-run repairs -> BACKED",
      got == ("BACKED", "written-this-session"), "/".join(got))

for name, later in [
    ("suffix_bak", lambda s, t: f"check {t}.bak"),
    ("other_dir", lambda s, t: f"check {s.dir}/other/report.md"),
    ("printf_text", lambda s, t: f'printf "%s\\n" "check {t}"'),
]:
    s, t = command_case(name, later)
    got = s.finish(f"I fixed `{t}`.")
    check(f"C3 decisive: {name} success does not erase the target failure",
          got[0] in ("CONTRADICTED", "UNVERIFIABLE"), "/".join(got))
    check(f"C3 {name}: abstains as repair-unbound",
          got == ("UNVERIFIABLE", "repair-unbound"), "/".join(got))

s, t = command_case("no_repair", None)
got = s.finish(f"I fixed `{t}`.")
check("C3 keep: standing target failure contradicts",
      got == ("CONTRADICTED", "later-error"), "/".join(got))

s, t = command_case("exact_write_positive", None)
s.tool("write_file", {"path": str(t)}, lambda: t.write_text("repaired work, longer\n"))
got = s.finish(f"I fixed `{t}`.")
check("C3 keep: exact-path write repair -> BACKED",
      got == ("BACKED", "written-this-session"), "/".join(got))

s, t = command_case("bak_then_rerun", lambda s, t: f"check {t}.bak")
s.tool("terminal", {"command": f"check {t}"}, status="ok", output="target check passed")
got = s.finish(f"I fixed `{t}`.")
check("C3 keep: unrelated success, then identical re-run -> BACKED",
      got == ("BACKED", "written-this-session"), "/".join(got))

s, t = command_case("rerun_then_fail", lambda s, t: f"check {t}")
s.tool("terminal", {"command": f"check {t}"}, status="error", output="target check failed again")
got = s.finish(f"I fixed `{t}`.")
check("C3 keep: a failure after the repair stands",
      got == ("CONTRADICTED", "later-error"), "/".join(got))

shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print(f"  FAILED {len(fails)}: {', '.join(fails)}")
    sys.exit(1)
print("  ok — scope counts are admission only; only exact repairs cancel a target failure")

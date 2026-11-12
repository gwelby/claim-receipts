"""PR #153708 review (teknium1, 2026-11-11): profile-correct paths and session-scoped /claim-receipts.

1 — paths: the ledger root and the transcript database must come from the ACTIVE profile's Hermes home
    (hermes_constants.get_hermes_home()), resolved at call time, not ~/.hermes fixed at import.
2 — /claim-receipts: on a messaging gateway it must show only the calling chat's own ledger: no
    newest-of-any-session fallback, and no reading another chat by naming its session. The newest-
    ledger fallback stays for the local CLI.

The handler is called the way Hermes calls it: hermes_cli/plugin_command_dispatch.py passes raw_args
plus only the context keywords (source, session_id, session_key, platform) the handler declares.
Run against d2e41bb this test must fail (old handler ignores the session; old paths are fixed).
"""
import importlib.util
import inspect
import os
import pathlib
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:70} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-pr153708-"))
for k in ("RECEIPTS_ROOT", "RECEIPTS_TRANSCRIPT_DB", "HERMES_HOME"):
    os.environ.pop(k, None)
# Any "~" fallback (including the pre-fix code this test is run against as a control) must land in
# the temp folder, never in the real ~/.hermes.
os.environ["HOME"] = str(TMP / "home")

# A stand-in for Hermes's hermes_constants whose active home can change between calls, the way a
# gateway switches profiles per request.
fake = types.ModuleType("hermes_constants")
fake.HOME = TMP / "profile-a"
fake.get_hermes_home = lambda: fake.HOME
sys.modules["hermes_constants"] = fake

spec = importlib.util.spec_from_file_location("claim_receipts_pr", ROOT / "__init__.py",
                                              submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules["claim_receipts_pr"] = plugin
spec.loader.exec_module(plugin)
ledger = sys.modules["claim_receipts_pr.receipts.ledger"]
transcript = importlib.import_module("claim_receipts_pr.receipts.transcript")

print("\n1 — paths follow the active profile, resolved per call")
fake.HOME = TMP / "profile-a"
a_root = ledger.root()
check("ledger root is <profile-a>/plugin-data/receipts", a_root == str(TMP / "profile-a" / "plugin-data" / "receipts"), a_root)
fake.HOME = TMP / "profile-b"
b_root = ledger.root()
check("after a profile switch the ledger root follows (not cached at import)",
      b_root == str(TMP / "profile-b" / "plugin-data" / "receipts"), b_root)
db = getattr(transcript, "db_location", lambda: "")()
check("transcript database is <active profile>/state.db", db == str(TMP / "profile-b" / "state.db"), db)
os.environ["RECEIPTS_ROOT"] = str(TMP / "override")
check("RECEIPTS_ROOT still overrides", ledger.root() == str(TMP / "override"), ledger.root())
os.environ.pop("RECEIPTS_ROOT")


def invoke(handler, raw_args, **context):
    """hermes_cli/plugin_command_dispatch.invoke_plugin_command, reduced to its keyword rule."""
    params = list(inspect.signature(handler).parameters.values())[1:]
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return handler(raw_args, **context)
    names = {p.name for p in params}
    return handler(raw_args, **{k: v for k, v in context.items() if k in names})


def record(session_id, command):
    kw = dict(tool_name="terminal", args={"command": command}, session_id=session_id, tool_call_id=f"{session_id}-1")
    ledger.pre_tool_call(**kw)
    ledger.post_tool_call(**kw, result="ok", status="ok")


print("\n2 — /claim-receipts shows only the caller's own session on a gateway")
fake.HOME = TMP / "gateway-profile"
record("chat-A", "echo SECRET_OF_A")
record("chat-B", "echo SECRET_OF_B")          # written last: the newest ledger on the machine
gw = dict(source=object(), session_key="k", platform="telegram")
out = invoke(plugin._handle_slash, "", session_id="chat-A", **gw)
check("gateway, chat A, no argument: shows A's command", "SECRET_OF_A" in out, out.splitlines()[0][:60])
check("gateway, chat A, no argument: never shows B's command", "SECRET_OF_B" not in out)
out = invoke(plugin._handle_slash, "chat-B", session_id="chat-A", **gw)
check("gateway, chat A naming chat B: refused, B not shown", "SECRET_OF_B" not in out, out[:70])
out = invoke(plugin._handle_slash, "", session_id="", **gw)
check("gateway with no session id: nothing shown (no newest fallback)",
      "SECRET_OF_A" not in out and "SECRET_OF_B" not in out, out[:70])
out = invoke(plugin._handle_slash, "", session_id="chat-C", **gw)
check("gateway, chat C with no ledger: B's newest ledger is not shown", "SECRET_OF_B" not in out, out[:70])
cli = dict(source=None, session_key="", platform="cli")
out = invoke(plugin._handle_slash, "", session_id="", **cli)
check("local CLI with no session: newest ledger fallback kept, and labelled",
      "SECRET_OF_B" in out and "newest ledger" in out, out.splitlines()[0][:70])
out = invoke(plugin._handle_slash, "chat-A", session_id="", **cli)
check("local CLI naming a session: that session", "SECRET_OF_A" in out and "SECRET_OF_B" not in out)

print(f"\n  {len(fails)} failure(s)" if fails else "\n  ok — profile paths per call; gateway sees only its own chat")
sys.exit(1 if fails else 0)

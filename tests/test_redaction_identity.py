"""Secret redaction in the ledger, without losing command identity.

Two properties, and the tests are written so that each can fail on its own:

1. A credential typed into a terminal call must not reach the ledger file in the clear.
2. Two commands that differ ONLY in a credential must still be distinguishable, because
   `judge._same_check` decides whether a failing check was re-run by comparing commands. Redact the
   text and nothing else, and `Bearer AAA` == `Bearer BBB` — a different command would pose as the
   identical failing one re-run, which is rule C3 (the rule several audit rounds hardened).

The negative controls matter as much as the positives: a redactor that also eats ordinary words
(`tokenizer.py`, `ls -la`, `grep -q good report.md`) would silently damage the path and verb parsing
the judge depends on. Those cases are asserted here as NOT redacted.
"""
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from receipts import judge, ledger, redact  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<62} {detail}")
    if not cond:
        fails.append(name)


print("1 — redaction removes credential VALUES and nothing else")
cases = [
    ('curl -H "Authorization: Bearer abc123def456ghi789" https://api.example.com/x',
     "Bearer abc123def456ghi789", True),
    ("export GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123", "ghp_abcdefghijklmnopqrstuvwxyz0123", True),
    ("mysql --password=hunter2 -u root", "hunter2", True),
    ("curl https://user:s3cr3t@example.com/path", "s3cr3t", True),
    ("AWS_SECRET_ACCESS_KEY='abc/def+ghi' python3 run.py", "abc/def+ghi", True),
]
for cmd, secret, must_vanish in cases:
    out = redact.redact_command(cmd)
    check(f"redacted: {cmd[:44]}", (secret not in out) == must_vanish, out[:58])

print("\n2 — NEGATIVE: ordinary commands and filenames are untouched")
untouched = [
    "ls -la /mnt/d/Hermes/register",
    "grep -q good report.md",
    "python3 -m pytest tests/tokenizer_test.py",
    "cat receipts/paths.py",
    "find /mnt/d/Aria -maxdepth 2 -name '*.py' -print",
    "python3 sk-learn_demo.py",                     # `sk-` at 8 chars ate this; now it must not
    "grep -rn 'session_id' receipts/claims.py",
]
for cmd in untouched:
    out = redact.redact_command(cmd)
    check(f"unchanged: {cmd[:44]}", out == cmd, "" if out == cmd else f"became {out[:50]}")

real_sk = "curl -H 'x-api-key: sk-proj-abcdefghijklmnopqrstuvwx' https://api.example.com"
check("a real sk- token is still redacted", "abcdefghijklmnopqrstuvwx" not in redact.redact_command(real_sk),
      redact.redact_command(real_sk)[:52])

print("\n3 — the digest distinguishes commands that differ only in a secret")
a = "curl -H 'Authorization: Bearer AAA111aaa111' https://x/y"
b = "curl -H 'Authorization: Bearer BBB222bbb222' https://x/y"
check("same display text after redaction", redact.redact_command(a) == redact.redact_command(b),
      redact.redact_command(a)[:48])
check("different digests", redact.command_digest(a) != redact.command_digest(b))
check("identical commands share a digest", redact.command_digest(a) == redact.command_digest(a))

print("\n4 — _same_check: identity without leaking the secret")
cwd = "/home/greg/work/proj"
ev_a = {"cmd": redact.redact_command(a), "cmd_sha256": redact.command_digest(a), "cwd": cwd}
ev_b = {"cmd": redact.redact_command(b), "cmd_sha256": redact.command_digest(b), "cwd": cwd}
ev_a2 = {"cmd": redact.redact_command(a), "cmd_sha256": redact.command_digest(a), "cwd": cwd}
check("same command, different secrets -> NOT the same check", judge._same_check(ev_b, ev_a) is False)
check("same command, same secret -> IS the same check", judge._same_check(ev_a2, ev_a) is True)

print("\n5 — legacy and mixed records abstain rather than guess")
legacy_a = {"cmd": a, "cwd": cwd}                      # no digest: written before this change
legacy_a2 = {"cmd": a, "cwd": cwd}
check("two legacy records still compare by text", judge._same_check(legacy_a2, legacy_a) is True)
legacy_b = {"cmd": b, "cwd": cwd}
check("two legacy records with different text are different", judge._same_check(legacy_b, legacy_a) is False)
check("mixed (digest vs legacy) abstains", judge._same_check(ev_a, legacy_a) is False)

print("\n6 — end to end: the ledger file never contains the secret")
d = tempfile.mkdtemp(prefix="redact-")
os.environ["RECEIPTS_ROOT"] = d
S = "sess-redact-1"
secret = "ghp_ZZZZsecretsecretsecret012345"
cmd = f"export GITHUB_TOKEN={secret} && ls /mnt/d/Hermes"
ledger.post_tool_call(tool_name="terminal", args={"command": cmd, "cwd": "/mnt/d/Hermes"},
                      session_id=S, task_id="", tool_call_id="c1", duration_ms=5, status="ok")
raw = pathlib.Path(ledger.session_file(S)).read_text()
check("secret is absent from the ledger bytes", secret not in raw)
rec = json.loads(raw.strip().splitlines()[-1])
check("record keeps a redacted display string", "[REDACTED]" in (rec.get("command") or ""))
check("record keeps the exact-original digest", rec.get("command_sha256") == redact.command_digest(cmd))
check("digest is not reversible to the secret", secret not in (rec.get("command_sha256") or ""))

print("\n7 — a failing check re-run still repairs (the rule this change must not break)")
ok_ev = {"cmd": "python3 check.py", "cmd_sha256": redact.command_digest("python3 check.py"), "cwd": cwd, "ok": True}
bad_ev = {"cmd": "python3 check.py", "cmd_sha256": redact.command_digest("python3 check.py"), "cwd": cwd, "ok": False}
check("identical re-run of the same command repairs", judge._same_check(ok_ev, bad_ev) is True)

print()
if fails:
    print(f"FAILED {len(fails)}: {fails}")
    sys.exit(1)
print("ok — secrets stay out of the ledger; identity survives")

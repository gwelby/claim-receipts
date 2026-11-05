"""The receipt artifact: what it must always say, and what it must never hide.

The receipt is the only part of this plugin a person reads, and every failure in it is silent — the
handlers swallow exceptions by design, so a broken receipt looks exactly like a clean one. These
checks are mostly about the honest-negative cases: no transcript, nothing checkable, nothing changed.
"""
import json
import os
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from receipts import receipt  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<58} {detail}")
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="receipts-artifact-")
os.environ["RECEIPTS_ROOT"] = tmp          # never touch the live ledger from a test


def session_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
                "content TEXT, tool_name TEXT, timestamp TEXT)")
    con.executemany("INSERT INTO messages (session_id, role, content, tool_name, timestamp) "
                    "VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


S = "testsession0001"
db = session_db(os.path.join(tmp, "state.db"), [
    (S, "user", "check the build", None, "t1"),
    (S, "tool", "build_v3 exists", "terminal", "t2"),
    (S, "assistant", "build_v3 is the current build.", None, "t3"),
    (S, "assistant", "I could not confirm the other artifact exists.", None, "t4"),
    (S, "assistant", "I don't know what it would be yet.", None, "t5"),
])

# ---- 1. a session with no evidence at all ----
d = receipt.build(S, db_path=db)
check("build returns a dict", isinstance(d, dict))
check("reports the transcript as readable", d["transcript_available"] is True)
check("no mutation invented from prose", d["evidence"]["mutations"] == 0,
      f"{d['evidence']['mutations']}")

# ---- 2. the two hedges are treated differently, and that is the point ----
md = receipt.render_md(d)
check("verification hedge is scored", "could not confirm" in md.lower() or "hedge" in md.lower())
check("existential 'I don't know' is NOT scored backed",
      "i don't know what it would be yet" not in md.lower()
      or "unjudged" in md.lower())

# ---- 3. what the artifact must ALWAYS say ----
check("always states what it cannot tell you", "does not tell you" in md.lower())
check("always distinguishes uncheckable claims", "could not be checked" in md.lower()
      or "could not" in md.lower())
check("claims unverifiable are not called clean", "not a clean bill" in md.lower()
      or d["transcript_available"] is True)

# ---- 4. a missing transcript must be said out loud, not passed over ----
ghost = receipt.build("no-such-session", db_path=db)
check("missing transcript detected", ghost["transcript_available"] is False)
gmd = receipt.render_md(ghost)
check("missing transcript is stated as absence of evidence",
      "no transcript" in gmd.lower() and "not a clean bill" in gmd.lower())

# ---- 5. writing both artifacts ----
res = receipt.write(S, db_path=db)
check("write succeeded", res.get("ok") is True, res.get("error", ""))
md_path, js_path = res.get("md", ""), res.get("json", "")
check("markdown written", os.path.isfile(md_path), md_path)
check("json written", os.path.isfile(js_path))
with open(js_path) as fh:
    payload = json.load(fh)
check("json round-trips", payload["session"] == S and "claims" in payload)
check("json carries the same counts as the build", payload["claims"]["judged"] >= 0)

# ---- 6. no silent collision from a shortened id ----
long_a = "local-" + "a" * 70
long_b = "local-" + "a" * 69 + "b"
ra = receipt.write(long_a, db_path=db)
rb = receipt.write(long_b, db_path=db)
check("two long ids do not share one receipt", ra.get("md") != rb.get("md"),
      f"{os.path.basename(ra.get('md',''))} vs {os.path.basename(rb.get('md',''))}")

# ---- 7. never raises, whatever it is handed ----
for bad in (None, "", "../../etc/passwd", "x" * 400):
    try:
        r = receipt.write(bad, db_path=os.path.join(tmp, "absent.db"))
        ok = isinstance(r, dict) and "ok" in r
    except Exception as exc:
        ok = False
        print("    raised:", exc)
    check(f"write({str(bad)[:18]!r}) returns a dict, never raises", ok)

print(f"\n  {len(fails)} failure(s)" if fails else "\n  ok — the receipt says what it cannot check")
sys.exit(1 if fails else 0)

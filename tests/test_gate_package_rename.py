#!/usr/bin/env python3
"""Locks the R7 rename and the package builder's shell syntax into the canonical suite.

`make test` never executed scripts/gate_package.sh, so a green suite said nothing about it — an ad-hoc
check in scratch covered it once and then died. This makes the property permanent.

The assertion is on the PROPERTY, not on a line number: a future edit that reintroduces a
truth-label-free quantity under a name implying precision must fail here.
"""
import pathlib
import re
import subprocess

GATE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "gate_package.sh"
SRC = GATE.read_text()
LINES = SRC.splitlines()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + str(detail)) if detail else ''}")
    if not ok:
        fails += 1


print("gate package — shell syntax")
r = subprocess.run(["bash", "-n", str(GATE)], capture_output=True, text=True)
check("bash -n", r.returncode == 0, r.stderr.strip()[:80])

print("\nR7 — the share must never again be named a false-positive rate")
check("fp_rate gone", "fp_rate" not in SRC)
check("fp_threshold gone", "fp_threshold" not in SRC)
check("FP_rate label gone", "FP_rate" not in SRC)
check("unbacked_claim_share present", "unbacked_claim_share" in SRC)
check("not_a_false_positive_rate disavowal present", "not_a_false_positive_rate" in SRC)

print("\nthe console statement carries the honest name (f-string spans 3 lines)")
i = [n for n, ln in enumerate(LINES) if "day3 counts from" in ln]
check("statement found exactly once", len(i) == 1, str(len(i)))
stmt = " ".join(LINES[i[0]:i[0] + 3]) if i else ""
check("no bare 'fp {'", not re.search(r"\bfp\s*\{", stmt), stmt[:60])
check("names unbacked-claim share", "unbacked-claim share" in stmt, stmt[-60:])

print(f"\n{'FAIL' if fails else 'ok'} — {fails} failed")
raise SystemExit(1 if fails else 0)

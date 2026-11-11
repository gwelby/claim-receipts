"""C4 gate: the acceptance exit must reject every regression it lists, not only the original quota.

Codex (2026-11-09, fdb8f87): with runner, fixture and expectations unchanged, forcing ONLY the added
aggregate regression favorable (case-r2a) or making the honest deletion falsely CONTRADICTED
(case-r3b) each scored 34/35 and exited 0. Each mutant here wraps receipts.judge.judge in a FRESH
process and forces named cases' verdicts, then runs tests/test_acceptance.py exactly as `make
acceptance` does. The runner, fixture and expectations are never edited.

Cases are selected by fixture id (Evidence.from_fixture is wrapped to remember which case built each
Evidence), not by claim kind, so a judge change in another lane cannot silently turn a mutant into a
no-op; each mutant must also show its injected verdict on every targeted case or the test fails.

(Named without "acceptance" so `make test` runs it; the Makefile skips files matching *acceptance*.)
"""
import pathlib
import runpy
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "test_acceptance.py"

# mode -> ({case id: forced verdict}, expected exit is zero?)
MUTANTS = {
    # paired positive control: the unmutated suite must pass
    "none": ({}, True),
    # Codex C4 rows (same cases Codex's kind-selected mutants hit: see acceptance/*.stdout)
    "original_quota": ({"case-01": "BACKED", "case-07": "BACKED"}, False),
    "aggregate": ({"case-r2a": "BACKED"}, False),
    "honest_deletion": ({"case-r3b": "CONTRADICTED"}, False),
    # mandatory original positive fails while the original quota stays 7/8
    "mandatory_positive": ({"case-06": "UNBACKED"}, False),
    # an added positive named "POSITIVE:" (not "POSITIVE CONTROL") abstains
    "added_positive": ({"case-r4i": "UNVERIFIABLE"}, False),
    # paired positive control: the original 7/8 allowance is kept — one non-positive original miss
    "original_one_miss": ({"case-01": "BACKED"}, True),
}


def _mutant_main(mode):
    """Runs inside the child process: wrap the judge, then execute the runner as __main__."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    from receipts import judge as j
    from receipts.evidence import Evidence

    force = MUTANTS[mode][0]
    case_of = {}
    real_from_fixture = Evidence.from_fixture.__func__
    real_judge = j.judge

    def from_fixture(cls, data):
        ev = real_from_fixture(cls, data)
        case_of[id(ev)] = data.get("id")
        return ev

    def judge(claim, ev, **kw):
        forced = force.get(case_of.get(id(ev)))
        if forced:
            return j.Verdict(forced, f"injected-{mode}")
        return real_judge(claim, ev, **kw)

    Evidence.from_fixture = classmethod(from_fixture)
    j.judge = judge
    try:
        runpy.run_path(str(RUNNER), run_name="__main__")
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    sys.stdout.flush()
    raise SystemExit(code)


fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<58} {detail}")
    if not cond:
        fails.append(name)


def main():
    for mode, (force, want_zero) in MUTANTS.items():
        p = subprocess.run([sys.executable, "-B", str(pathlib.Path(__file__).resolve()),
                            "--mutant", mode], capture_output=True, text=True, timeout=300)
        out = p.stdout
        # The mutation must actually have reached every targeted case (no vacuous mutant).
        injected = out.count(f"injected-{mode}")
        bar_line = next((ln.strip() for ln in out.splitlines() if "bar met:" in ln), "(no bar line)")
        check(f"{mode}: injected into all {len(force)} targeted case(s)",
              injected == len(force), f"saw {injected}")
        check(f"{mode}: exit {'0' if want_zero else 'nonzero'}",
              (p.returncode == 0) == want_zero, f"exit={p.returncode}; {bar_line}")
        if p.stderr.strip():
            check(f"{mode}: no stderr", False, p.stderr.strip().splitlines()[-1][:60])

    # The fixture-binding helper: the runner reads roles from expectations, so they must be sealed.
    sys.path.insert(0, str(ROOT / "tests"))
    from test_acceptance import fixture_digest_problem
    import hashlib
    blob = b'{"cases": []}'
    good = hashlib.sha256(blob).hexdigest() + "  fixtures/acceptance.json\n"
    check("digest: matching sha256 line accepted", fixture_digest_problem(blob, good) is None)
    check("digest: changed bytes refused", fixture_digest_problem(blob + b" ", good) is not None)
    check("digest: empty record refused", fixture_digest_problem(blob, "") is not None)

    print(f"\n  {len(fails)} failed" if fails else "\n  all passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--mutant":
        _mutant_main(sys.argv[2])
    else:
        main()

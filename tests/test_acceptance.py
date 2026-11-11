"""Score Receipts against the sealed acceptance set.

Development tests, not validation: the engine's author has read these cases. The public claim rests
on a held-out set written by someone else, which does not exist yet.

Pass bar — every part is enforced in the exit status, independently (C4, Codex 2026-11-09):
  1. Fixture bound: fixtures/acceptance.json must match fixtures/acceptance.json.sha256. Roles below are
     read from each case's expected verdict, so the expectations themselves must be the sealed ones.
  2. Original eight (case-01..case-08, all present, exactly once): 7/8 verdicts, and BOTH original
     positive controls (#6 honest hedge, #8 fully backed) BACKED as expected. Unchanged policy.
  3. Every added regression case (any id outside the original eight) matches its expected verdict.
     None of them is pooled into a quota: one aggregate or deletion regression fails the bar alone.
  4. No case where honest work is called CONTRADICTED. "Honest work" is a ROLE read from the case's
     expectation (expected verdict BACKED), never from a word in its name — case-r3b is named
     "NEGATIVE: ..." yet expects BACKED, and the old name filter could not see it contradicted.
"""
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from receipts.evidence import Evidence      # noqa: E402
from receipts.judge import extract_claims, judge  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance.json"
FIX_SHA = ROOT / "fixtures" / "acceptance.json.sha256"
ORIGINAL_IDS = tuple(f"case-0{i}" for i in range(1, 9))
HONEST_VERDICT = "BACKED"   # the favorable verdict: a case that expects it is honest work


def fixture_digest_problem(data: bytes, sha_text: str):
    """None when `data` matches the first field of a sha256sum line, else a reason string."""
    fields = (sha_text or "").split()
    if not fields:
        return "no recorded sha256"
    want, got = fields[0].lower(), hashlib.sha256(data).hexdigest()
    return None if got == want else f"sha256 {got[:16]}… != recorded {want[:16]}…"


def is_honest_work(case) -> bool:
    """Role by expectation, not by name."""
    return case["expect"]["verdict"] == HONEST_VERDICT


def score_bar(rows):
    """Evaluate every part of the bar from scored rows. Pure; returns a dict of parts + `bar_met`."""
    ids = [r[0]["id"] for r in rows]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    orig = [r for r in rows if r[0]["id"] in ORIGINAL_IDS]
    added = [r for r in rows if r[0]["id"] not in ORIGINAL_IDS]
    orig_complete = sorted(r[0]["id"] for r in orig) == sorted(ORIGINAL_IDS)

    orig_hits = sum(1 for r in orig if r[3] == "PASS")
    orig_pos = [r for r in orig if is_honest_work(r[0])]
    # "BOTH positive controls BACKED" — an empty set must not pass by vacuous truth.
    orig_pos_ok = len(orig_pos) >= 2 and all(r[3] == "PASS" for r in orig_pos)

    added_fail = [r[0]["id"] for r in added if r[3] != "PASS"]
    added_ok = len(added) >= 1 and not added_fail

    honest = [r for r in rows if is_honest_work(r[0])]
    honest_ok = len(honest) >= 2 and all(r[3] == "PASS" for r in honest)
    honest_contra = [r[0]["id"] for r in honest if r[1] and r[1].verdict == "CONTRADICTED"]
    # Diagnostic only: any CONTRADICTED that was not expected (the original-eight 7/8 allowance
    # still tolerates one non-honest original miss; added cases are already required in full).
    false_contra = [r[0]["id"] for r in rows if r[1] and r[1].verdict == "CONTRADICTED"
                    and r[2]["verdict"] != "CONTRADICTED"]

    orig_bar = orig_complete and orig_hits >= 7 and orig_pos_ok
    bar_met = (not dup_ids and orig_bar and added_ok and honest_ok and not honest_contra)
    return {"dup_ids": dup_ids, "orig_complete": orig_complete, "orig_hits": orig_hits,
            "orig_total": len(orig), "orig_pos": len(orig_pos), "orig_pos_ok": orig_pos_ok,
            "orig_bar": orig_bar, "added_total": len(added), "added_fail": added_fail,
            "added_ok": added_ok, "honest_total": len(honest), "honest_ok": honest_ok,
            "honest_contra": honest_contra, "false_contra": false_contra, "bar_met": bar_met}


def run(verbose=True):
    raw = FIX.read_bytes()
    digest_problem = fixture_digest_problem(raw, FIX_SHA.read_text() if FIX_SHA.exists() else "")
    data = json.loads(raw)
    rows, hits = [], 0
    for case in data["cases"]:
        claims = extract_claims(case["claim_text"])
        ev = Evidence.from_fixture(case)
        expected = case["expect"]

        if not claims:
            rows.append((case, None, expected, "MISS-DETECTION"))
            continue
        claim = claims[0]
        if case.get("subject"):
            claim.subject = case["subject"]          # subject resolution is out of scope here
        scope = case.get("scope") or {}
        v = judge(claim, ev, claimed_count=scope.get("claimed"),
                  evidence_count=scope.get("evidence"))
        got = v.verdict
        ok = got == expected["verdict"]
        hits += 1 if ok else 0
        rows.append((case, v, expected, "PASS" if ok else "MISS"))

    if verbose:
        for case, v, expected, state in rows:
            mark = {"PASS": "PASS", "MISS": "MISS", "MISS-DETECTION": "NO-CLAIM"}[state]
            got = f"{v.verdict}/{v.reason}" if v else "(no claim detected)"
            print(f"  [{mark:8}] {case['id']}  {case['name'][:52]}")
            print(f"             expected {expected['verdict']}/{expected['reason']}")
            print(f"             got      {got}")
            if v and v.detail:
                print(f"             detail   {v.detail[:78]}")
            if case.get("known_gap"):
                print(f"             KNOWN GAP {case['known_gap'][:70]}")

    # R6 (Codex, 2026-11-06): the bar was PRINTED but never enforced — __main__ exited on
    # `hits >= 7` alone. Compute unconditionally (not inside `if verbose:`) and exit on the bar.
    #
    # C4 (Codex, 2026-11-09): rev 5 enforced only the original quota and four controls selected by
    # the words "POSITIVE CONTROL" in their names, so a forced-favorable aggregate regression
    # (case-r2a) or a falsely CONTRADICTED honest deletion (case-r3b, named "NEGATIVE") scored
    # 34/35 and exited 0. Every added case is now required on its own, and honest work is
    # identified by its expected verdict. The original-eight 7/8 + both-positives policy is kept.
    total = len(rows)
    b = score_bar(rows)
    bar_met = b["bar_met"] and digest_problem is None

    if verbose:
        print(f"\n  score: {hits}/{total}")
        print(f"  fixture sha256 bound: {digest_problem is None}"
              + (f" ({digest_problem})" if digest_problem else ""))
        if b["dup_ids"]:
            print(f"  duplicate case ids: {', '.join(b['dup_ids'])}")
        print(f"  original eight: {b['orig_hits']}/{b['orig_total']} "
              f"(all eight present: {b['orig_complete']}; bar 7/8 + both positives: {b['orig_bar']})")
        print(f"  added regressions: {b['added_total'] - len(b['added_fail'])}/{b['added_total']} "
              f"(each required: {b['added_ok']})"
              + (f" failing: {', '.join(b['added_fail'])}" if b["added_fail"] else ""))
        print(f"  honest-work cases (expected {HONEST_VERDICT}) as expected: {b['honest_ok']} "
              f"({b['honest_total']} found)")
        print(f"  honest work wrongly CONTRADICTED: {len(b['honest_contra'])}"
              + (f" ({', '.join(b['honest_contra'])})" if b["honest_contra"] else ""))
        print(f"  any unexpected CONTRADICTED (diagnostic): {len(b['false_contra'])}"
              + (f" ({', '.join(b['false_contra'])})" if b["false_contra"] else ""))
        print(f"  bar met: {bar_met}")
    return hits, total, bar_met


if __name__ == "__main__":
    hits, total, bar_met = run()
    sys.exit(0 if bar_met else 1)

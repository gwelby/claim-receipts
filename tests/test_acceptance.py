"""Score Receipts against the sealed acceptance set.

Development tests, not validation: the engine's author has read these cases. The public claim rests
on a held-out set written by someone else, which does not exist yet.

Pass bar (agreed): 7/8 verdicts, BOTH positive controls BACKED (#6 honest hedge, #8 fully backed),
and no case where honest work is called CONTRADICTED.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from receipts.evidence import Evidence      # noqa: E402
from receipts.judge import extract_claims, judge  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance.json"


def run(verbose=True):
    data = json.loads(FIX.read_text())
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
    # `hits >= 7` alone, so the broken-hedge mutant scored 7/8 with positive controls False and
    # still exited 0. Worse, these were computed INSIDE `if verbose:`, so run(verbose=False)
    # never evaluated them at all. Compute unconditionally, return them, and exit on all three.
    #
    # Regression cases are additive (Codex, 2026-11-08): the ORIGINAL eight-case bar —
    # 7/8 plus both positive controls — is scored on the sealed case-0* set alone, so
    # new cases can never dilute it, and the aggregate bar still applies overall.
    total = len(rows)
    orig = [r for r in rows if r[0]["id"].startswith("case-0")]
    orig_hits = sum(1 for r in orig if r[3] == "PASS")
    orig_pos = [r for r in orig if "POSITIVE CONTROL" in r[0]["name"]]
    orig_pos_ok = len(orig_pos) >= 2 and all(
        r[1] is not None and r[1].verdict == r[2]["verdict"] for r in orig_pos)
    orig_contra = [r for r in orig
                   if r[1] and r[1].verdict == "CONTRADICTED"
                   and "POSITIVE CONTROL" in r[0]["name"]]
    orig_bar = orig_hits >= 7 and orig_pos_ok and not orig_contra

    positives = [r for r in rows if "POSITIVE CONTROL" in r[0]["name"]]
    # "BOTH positive controls BACKED" is the agreed bar — an empty positive set must NOT pass
    # by vacuous truth (all([]) is True), so require the count too.
    pos_ok = len(positives) >= 2 and all(
        r[1] is not None and r[1].verdict == r[2]["verdict"] for r in positives)
    contradict_honest = [r for r in rows
                         if r[1] and r[1].verdict == "CONTRADICTED"
                         and "POSITIVE CONTROL" in r[0]["name"]]
    bar_met = orig_bar and pos_ok and not contradict_honest

    if verbose:
        print(f"\n  score: {hits}/{total}")
        print(f"  original eight: {orig_hits}/{len(orig)} "
              f"(bar 7/8 + both positives: {orig_bar})")
        print(f"  positive controls BACKED: {pos_ok} ({len(positives)} found)")
        print(f"  honest work wrongly CONTRADICTED: {len(contradict_honest)}")
        print(f"  bar met: {bar_met}")
    return hits, total, bar_met


if __name__ == "__main__":
    hits, total, bar_met = run()
    sys.exit(0 if bar_met else 1)
